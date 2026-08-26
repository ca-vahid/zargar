"""Entrypoint: python -m zargar.main"""
from __future__ import annotations

import logging
import logging.handlers
import pathlib

import uvicorn

from .api.app import create_app
from .config import get_config


def main() -> None:
    config = get_config()
    # Always keep a rotating file log next to the package: the app usually runs
    # detached/hidden on Windows, and the 2026-08-25 feed outage was
    # undiagnosable because stdout went to a hidden window and nothing else.
    log_path = pathlib.Path(__file__).resolve().parent.parent / f"zargar-{config.port}.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        handlers=[logging.StreamHandler(), file_handler],
    )
    # Exposed to a network (phones via LAN/Tailscale) the token is the only gate —
    # never start reachable-and-open. Loopback (Tailscale Serve proxies to it) is fine.
    if config.host not in ("127.0.0.1", "localhost", "::1") and not (config.auth_token or config.google_client_id):
        raise SystemExit(
            f"refusing to bind {config.host}:{config.port} without sign-in — set ZARGAR_GOOGLE_CLIENT_ID "
            "(+ ZARGAR_GOOGLE_ALLOWED_EMAILS) or ZARGAR_AUTH_TOKEN in backend/.env (docs/AUTH.md)")
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
