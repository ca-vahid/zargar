"""Print a signed session token for local tooling (the mobile audit, Playwright
checks) while Google sign-in is enforced.

    python -m zargar.tools.mint_session [--email you@gmail.com] [--hours 2]

Signs with the same secret the running app uses (`ZARGAR_SESSION_SECRET`, else the
one persisted in the settings table), so the token is accepted as a cookie
(`zargar_session=<token>`), a bearer or `?token=`. The email must be on
`ZARGAR_GOOGLE_ALLOWED_EMAILS`. Loopback tooling only — never paste this anywhere."""
import argparse
import asyncio
import secrets
import time

import jwt
from sqlalchemy import select

from zargar.auth import SECRET_KEY
from zargar.config import AppConfig
from zargar.db import make_engine
from zargar.models import Setting


async def _secret(config: AppConfig) -> str:
    if config.session_secret:
        return config.session_secret
    engine = make_engine(config.database_url)
    try:
        async with engine.connect() as conn:
            row = (await conn.execute(select(Setting.value).where(Setting.key == SECRET_KEY))).scalar_one_or_none()
    finally:
        await engine.dispose()
    value = (row or {}).get("v") or ""
    if not value:
        raise SystemExit("no session secret yet — start the app once (it generates and persists one)")
    return str(value)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--email", default=None, help="allow-listed address (default: first on the allow list)")
    ap.add_argument("--hours", type=float, default=2.0)
    args = ap.parse_args()
    config = AppConfig()
    allowed = [e.strip().lower() for e in config.google_allowed_emails.split(",") if e.strip()]
    email = (args.email or (allowed[0] if allowed else "")).lower()
    if not email:
        raise SystemExit("no email: pass --email or set ZARGAR_GOOGLE_ALLOWED_EMAILS")
    if allowed and email not in allowed:
        raise SystemExit(f"{email} is not on the allow list — the app would reject it")
    now = int(time.time())
    token = jwt.encode({"sub": email, "name": "local tooling", "provider": "google", "iat": now,
                        "exp": now + int(args.hours * 3600), "sid": secrets.token_hex(8)},
                       asyncio.run(_secret(config)), algorithm="HS256")
    print(token)


if __name__ == "__main__":
    main()
