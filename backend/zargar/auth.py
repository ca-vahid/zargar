"""Sign-in.

Two ways in, both ending in the same place — an authenticated request:

  * **Google (OIDC).** The browser's "Sign in with Google" button hands us an
    ID token. We verify its signature against Google's published keys (JWKS),
    its audience (our OAuth client id) and issuer, insist the email is
    verified, and then — the actual access control — require the email to be
    on `ZARGAR_GOOGLE_ALLOWED_EMAILS`. Anyone else gets a clean 403 even with a
    perfectly valid Google account.
  * **Static API token** (`ZARGAR_AUTH_TOKEN`) — the old way; still honoured as
    a Bearer / `?token=` for scripts and the CLI tools.

A successful Google sign-in mints a **session**: an HS256 JWT signed with a
server secret, sent back as an HttpOnly cookie (`zargar_session`) *and* in the
JSON body so the WebSocket `?token=` and download links keep working. Sessions
expire after `ZARGAR_SESSION_DAYS` (30). Rotating the secret signs everyone out.

Microsoft / Office 365 are listed as providers but disabled — the login page
shows them greyed out until they're wired up.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Any, Callable

import jwt

log = logging.getLogger("zargar.auth")

COOKIE = "zargar_session"
SECRET_KEY = "system.session_secret"   # settings key holding the generated signing secret
GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]


class AuthError(Exception):
    """Sign-in refused; `status` is the HTTP code to answer with."""

    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.status = status


class AuthService:
    def __init__(self, config, settings, *, google_verifier: Callable[[str], dict] | None = None) -> None:
        self.config = config
        self.settings = settings
        self._jwks: jwt.PyJWKClient | None = None
        self._verify_google = google_verifier or self._verify_google_id_token
        self._secret_cache: str | None = None

    # ------------------------------------------------------------------ state
    @property
    def google_enabled(self) -> bool:
        return bool(self.config.google_client_id)

    @property
    def required(self) -> bool:
        """Anything configured means the API is closed to anonymous callers."""
        return bool(self.config.auth_token) or self.google_enabled

    def allowed_emails(self) -> set[str]:
        raw = str(self.config.google_allowed_emails or "")
        return {e.strip().lower() for e in raw.replace(";", ",").split(",") if e.strip()}

    def providers(self) -> list[dict]:
        return [
            {"id": "google", "label": "Google", "enabled": self.google_enabled,
             "note": None if self.google_enabled else "set ZARGAR_GOOGLE_CLIENT_ID"},
            {"id": "microsoft", "label": "Microsoft", "enabled": False, "note": "coming soon"},
            {"id": "office365", "label": "Office 365", "enabled": False, "note": "coming soon"},
        ]

    def public_config(self) -> dict:
        return {"required": self.required, "googleClientId": self.config.google_client_id or None,
                "providers": self.providers(), "sessionDays": int(self.config.session_days)}

    # ------------------------------------------------------------------ secret
    def secret(self) -> str:
        """Session-signing secret: env `ZARGAR_SESSION_SECRET`, else one generated
        once and kept in the settings table (so restarts don't sign you out)."""
        if self.config.session_secret:
            return self.config.session_secret
        if self._secret_cache:
            return self._secret_cache
        stored = self.settings.get(SECRET_KEY, "") if self.settings is not None else ""
        if stored:
            self._secret_cache = str(stored)
            return self._secret_cache
        self._secret_cache = secrets.token_urlsafe(48)
        if self.settings is not None:
            try:
                loop = asyncio.get_running_loop()
                self._persist_task = loop.create_task(self._persist_secret(self._secret_cache))
            except RuntimeError:
                pass  # no loop (tests / tools): in-memory secret is fine
        return self._secret_cache

    async def _persist_secret(self, value: str) -> None:
        # A hidden `system.*` key: never listed by /api/settings, never journaled,
        # never broadcast on the WS `system` topic. (Before 2026-08-26 this used an
        # undeclared key, `set()` raised, and every restart signed every device out.)
        try:
            await self.settings.set(SECRET_KEY, value, journal=False, broadcast=False)
        except Exception:
            log.exception("could not persist the session secret — sessions will not survive a restart")

    # ------------------------------------------------------------------ google
    def _verify_google_id_token(self, credential: str) -> dict:
        if self._jwks is None:
            self._jwks = jwt.PyJWKClient(GOOGLE_JWKS, cache_keys=True)
        key = self._jwks.get_signing_key_from_jwt(credential)
        return jwt.decode(credential, key.key, algorithms=["RS256"],
                          audience=self.config.google_client_id, issuer=GOOGLE_ISSUERS)

    def sign_in_google(self, credential: str) -> dict:
        if not self.google_enabled:
            raise AuthError("Google sign-in is not configured", 503)
        try:
            claims = self._verify_google(credential)
        except jwt.PyJWTError as exc:
            raise AuthError(f"Google token rejected: {exc}") from exc
        email = str(claims.get("email") or "").lower()
        if not email or not claims.get("email_verified", False):
            raise AuthError("Google did not confirm the email address")
        if email not in self.allowed_emails():
            log.warning("sign-in refused for %s (not on the allow list)", email)
            raise AuthError(f"{email} is not allowed to use this app", 403)
        return {"email": email, "name": str(claims.get("name") or email), "picture": claims.get("picture"),
                "provider": "google"}

    # ------------------------------------------------------------------ sessions
    def issue_session(self, user: dict) -> str:
        now = int(time.time())
        payload = {"sub": user["email"], "name": user.get("name"), "picture": user.get("picture"),
                   "provider": user.get("provider", "google"), "iat": now,
                   "exp": now + int(self.config.session_days) * 86400, "sid": secrets.token_hex(8)}
        return jwt.encode(payload, self.secret(), algorithm="HS256")

    def verify_session(self, token: str | None) -> dict | None:
        if not token:
            return None
        try:
            c = jwt.decode(token, self.secret(), algorithms=["HS256"])
        except jwt.PyJWTError:
            return None
        email = str(c.get("sub") or "").lower()
        # the allow list is live: removing an address ends its sessions too
        if self.google_enabled and email not in self.allowed_emails():
            return None
        return {"email": email, "name": c.get("name") or email, "picture": c.get("picture"),
                "provider": c.get("provider", "google"), "sid": c.get("sid")}

    def authenticate(self, *, bearer: str | None = None, cookie: str | None = None,
                     query_token: str | None = None) -> dict | None:
        """Who is this? None when nobody we trust. Order: static token, then any
        session token from the Authorization header, the cookie, or ?token=."""
        if not self.required:
            return {"email": "anonymous", "name": "local", "provider": "open"}
        static = self.config.auth_token
        if static:
            for t in (bearer, query_token):
                if t and secrets.compare_digest(t, static):
                    return {"email": "api-token", "name": "API token", "provider": "token"}
        for t in (bearer, cookie, query_token):
            user = self.verify_session(t)
            if user:
                return user
        return None


def cookie_kwargs(config, *, https: bool) -> dict[str, Any]:
    return {"httponly": True, "samesite": "lax", "secure": https, "path": "/",
            "max_age": int(config.session_days) * 86400}
